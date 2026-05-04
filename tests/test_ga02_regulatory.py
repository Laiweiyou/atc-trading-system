# -*- coding: utf-8 -*-
"""Tests for GA-02 阿呂+萱萱（監管分析）— Phase 3 Step 13."""
import io
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, r"C:\Users\jose8\atc-trading-system")

from trading_system.common.data_models import DebateResult, SubReport
from trading_system.common.message_bus import get_bus
from trading_system.squads.crypto.global_affairs.ga_02_regulatory import (
    RegulatoryAnalyst,
    RegulatorySection,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _reg_news(title, score=0.0, summary=""):
    """Pre-analyzed regulatory news item (skips fetch + VADER step)."""
    return {
        "title":                title,
        "summary":              summary,
        "source":               "Test",
        "published":            "",
        "sentiment_score":      score,
        "sentiment_confidence": abs(score),
    }


def _make_subreport(direction, confidence, stale=False):
    return SubReport(
        role_name="test", role_code="TEST",
        direction=direction, sub_confidence=confidence,
        reasoning="test", data_used={},
        timestamp=datetime.now(), staleness_flag=stale,
    )


def _fresh_analyst(mode):
    get_bus().clear()
    return RegulatoryAnalyst(mode, gateway=MagicMock())


def _fresh_section():
    get_bus().clear()
    return RegulatorySection(gateway=MagicMock())


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestGA02Regulatory(unittest.TestCase):

    # ── 01: 兩位分析員角色初始化 ──────────────────────────────────────────────

    def test_01_analyst_roles(self):
        alu      = _fresh_analyst("literal")
        xuanxuan = _fresh_analyst("contextual")

        self.assertEqual(alu.role_name,      "阿呂")
        self.assertEqual(alu.role_code,      "GA-02a")
        self.assertEqual(alu.mode,           "literal")

        self.assertEqual(xuanxuan.role_name, "萱萱")
        self.assertEqual(xuanxuan.role_code, "GA-02b")
        self.assertEqual(xuanxuan.mode,      "contextual")

        # 兩人都沒有 historical_events（不同於芸芸）
        self.assertFalse(hasattr(alu,      "historical_events"))
        self.assertFalse(hasattr(xuanxuan, "historical_events"))

    # ── 02: 阿呂 literal — 2 high_strictness → bearish 0.6 ───────────────────

    def test_02_literal_two_high_strictness_bearish_06(self):
        analyst = _fresh_analyst("literal")
        news = [
            _reg_news("SEC bans crypto exchanges nationwide",        score=-0.8),
            _reg_news("Criminal charges filed against exchange CEO", score=-0.7),
        ]

        report = analyst._literal_analysis(news)

        self.assertIsInstance(report, SubReport)
        self.assertEqual(report.direction,  "bearish")
        self.assertAlmostEqual(report.sub_confidence, 0.6, places=5)
        self.assertEqual(report.data_used["high_strictness"], 2)

    # ── 03: 阿呂 literal — 1 high_strictness → bearish 0.4 ───────────────────

    def test_03_literal_one_high_strictness_bearish_04(self):
        analyst = _fresh_analyst("literal")
        news = [_reg_news("Exchange CEO indicted by DOJ", score=-0.6)]

        report = analyst._literal_analysis(news)

        self.assertEqual(report.direction,  "bearish")
        self.assertAlmostEqual(report.sub_confidence, 0.4, places=5)
        self.assertEqual(report.data_used["high_strictness"], 1)

    # ── 04: 阿呂 literal — 1 medium_strictness → bearish 0.15 ────────────────

    def test_04_literal_medium_strictness_bearish_015(self):
        analyst = _fresh_analyst("literal")
        news = [_reg_news("SEC files lawsuit against Binance", score=-0.4)]

        report = analyst._literal_analysis(news)

        self.assertEqual(report.direction,  "bearish")
        self.assertAlmostEqual(report.sub_confidence, 0.15, places=5)
        self.assertEqual(report.data_used["medium_strictness"], 1)

    # ── 05: 阿呂 literal — 2 low_strictness，high=0 → bullish 0.2 ─────────────

    def test_05_literal_low_strictness_bullish_02(self):
        analyst = _fresh_analyst("literal")
        news = [
            _reg_news("SEC proposed new crypto framework",                     score=0.1),
            _reg_news("CFTC comment period on digital assets guideline opens", score=0.2),
        ]

        report = analyst._literal_analysis(news)

        self.assertEqual(report.direction,  "bullish")
        self.assertAlmostEqual(report.sub_confidence, 0.2, places=5)
        self.assertEqual(report.data_used["low_strictness"],  2)
        self.assertEqual(report.data_used["high_strictness"], 0)

    # ── 06: 阿呂 literal — 無關鍵字 → 無訊號 → neutral 0.3 ───────────────────

    def test_06_literal_no_keywords_neutral_03(self):
        analyst = _fresh_analyst("literal")
        news = [_reg_news("Bitcoin price reaches new all-time high today", score=0.5)]

        report = analyst._literal_analysis(news)

        self.assertEqual(report.direction,  "neutral")
        self.assertAlmostEqual(report.sub_confidence, 0.3, places=5)

    # ── 07: 萱萱 contextual — 2 strong → bearish 0.5 ─────────────────────────

    def test_07_contextual_two_strong_enforcement_bearish_05(self):
        analyst = _fresh_analyst("contextual")
        # score=0.0 keeps avg_sentiment neutral so only keyword signal fires
        news = [
            _reg_news("Exchange CEO arrested in New York",    score=0.0),
            _reg_news("FBI raids crypto firm headquarters",   score=0.0),
        ]

        report = analyst._contextual_analysis(news)

        self.assertEqual(report.direction,  "bearish")
        self.assertAlmostEqual(report.sub_confidence, 0.5, places=5)
        self.assertEqual(report.data_used["strong_enforcement_signals"], 2)

    # ── 08: 萱萱 contextual — 2 weak → bullish 0.3 ───────────────────────────

    def test_08_contextual_two_weak_enforcement_bullish_03(self):
        analyst = _fresh_analyst("contextual")
        # score=0.0 keeps avg_sentiment neutral so only keyword signal fires
        news = [
            _reg_news("SEC case against Ripple dropped by court",      score=0.0),
            _reg_news("CFTC charges against broker dismissed by judge", score=0.0),
        ]

        report = analyst._contextual_analysis(news)

        self.assertEqual(report.direction,  "bullish")
        self.assertAlmostEqual(report.sub_confidence, 0.3, places=5)
        self.assertEqual(report.data_used["weak_enforcement_signals"], 2)

    # ── 09: 萱萱 contextual — avg_sentiment > 0.3 → bullish 0.3 ──────────────

    def test_09_contextual_positive_avg_sentiment_bullish(self):
        analyst = _fresh_analyst("contextual")
        # No weak/strong keywords; avg_sentiment = 0.6 > 0.3
        news = [
            _reg_news("Crypto regulation update favors market growth",  score=0.6),
            _reg_news("Regulatory clarity welcomed by crypto industry", score=0.6),
        ]

        report = analyst._contextual_analysis(news)

        self.assertEqual(report.direction,  "bullish")
        self.assertAlmostEqual(report.sub_confidence, 0.3, places=5)
        self.assertAlmostEqual(report.data_used["avg_sentiment"], 0.6, places=5)

    # ── 10: 萱萱 contextual — 強弱訊號並存 → 不確定 → bearish 0.45 ───────────

    def test_10_contextual_uncertainty_strong_and_weak_signals(self):
        analyst = _fresh_analyst("contextual")
        # strong=1 → bearish 0.25; weak=1 → bullish 0.15; uncertainty → bearish 0.2
        # bearish_w=0.45, bullish_w=0.15 → 0.45 > 0.15*1.2 → bearish, conf=0.45
        news = [
            _reg_news("Exchange CEO indicted for fraud",  score=-0.8),
            _reg_news("Minor crypto case dismissed",      score=0.3),
        ]

        report = analyst._contextual_analysis(news)

        self.assertEqual(report.direction,  "bearish")
        self.assertEqual(report.data_used["strong_enforcement_signals"], 1)
        self.assertEqual(report.data_used["weak_enforcement_signals"],   1)
        self.assertAlmostEqual(report.sub_confidence, 0.45, places=5)

    # ── 11: 兩人方向一致 → agreed ────────────────────────────────────────────

    def test_11_agreed_both_bearish(self):
        section = _fresh_section()
        section.alu.analyze      = MagicMock(return_value=_make_subreport("bearish", 0.7))
        section.xuanxuan.analyze = MagicMock(return_value=_make_subreport("bearish", 0.6))

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type,  "agreed")
        self.assertEqual(result.final_direction, "bearish")
        self.assertAlmostEqual(result.final_confidence, 0.65, places=5)

    # ── 12: 大分歧 → dual_track → 保守採較嚴格方向 ──────────────────────────

    def test_12_dual_track_alu_bearish_xuanxuan_bullish(self):
        section = _fresh_section()
        section.alu.analyze      = MagicMock(return_value=_make_subreport("bearish", 0.6))
        section.xuanxuan.analyze = MagicMock(return_value=_make_subreport("bullish", 0.4))

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type,  "dual_track")
        self.assertEqual(result.final_direction, "bearish")
        self.assertAlmostEqual(result.final_confidence, 0.6 * 0.8, places=5)
        self.assertIsNotNone(result.key_disagreement)

    # ── 13: discussed_agreed（同向信心差距 > 0.2）──────────────────────────────

    def test_13_discussed_agreed_same_direction_large_gap(self):
        section = _fresh_section()
        section.alu.analyze      = MagicMock(return_value=_make_subreport("bearish", 0.8))
        section.xuanxuan.analyze = MagicMock(return_value=_make_subreport("bearish", 0.3))

        result = section.conduct_debate()

        self.assertEqual(result.consensus_type,  "discussed_agreed")
        self.assertEqual(result.final_direction, "bearish")
        expected = (0.8 ** 2 + 0.3 ** 2) / (0.8 + 0.3)
        self.assertAlmostEqual(result.final_confidence, expected, places=5)

    # ── 14: 真實 VADER 整合（mock fetch，直接跑情緒分析）─────────────────────

    def test_14_vader_integration_via_analyze(self):
        analyst = _fresh_analyst("literal")
        analyst.fetch_regulatory_news = MagicMock(return_value=[{
            "title":     "SEC bans all crypto trading platforms nationwide",
            "summary":   "Major regulatory crackdown expected to devastate markets",
            "source":    "Test",
            "published": "",
        }])

        report = analyst.analyze()

        self.assertIsInstance(report, SubReport)
        # 強烈負面監管新聞 → 不應 bullish
        self.assertNotEqual(report.direction, "bullish")

    # ── 15: conduct_debate 回傳完整 DebateResult ──────────────────────────────

    def test_15_conduct_debate_full_flow(self):
        section = _fresh_section()
        section.alu.analyze      = MagicMock(return_value=_make_subreport("neutral", 0.4))
        section.xuanxuan.analyze = MagicMock(return_value=_make_subreport("neutral", 0.4))

        result = section.conduct_debate()

        self.assertIsInstance(result, DebateResult)
        self.assertTrue(result.debate_id.startswith("GA-02-"))
        self.assertIn(result.consensus_type, ("agreed", "discussed_agreed", "dual_track"))
        self.assertIsInstance(result.report_a, SubReport)
        self.assertIsInstance(result.report_b, SubReport)
        self.assertEqual(len(section.debate_history), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
